import tensorflow as tf
import os
from time import time
import numpy as np


os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"
os.environ["CUDA_VISIBLE_DEVICES"]="0"

def prod(a):
    p = 1
    for e in a:
        p *= e
    return p

class Model:

    def __init__(self, train_data, n_titles, n_skills, max_skills, batcher, test_data=None, train_targets=None, test_targets=None,
                 use_dropout=True, num_layers=1, keep_prob=0.5, hidden_dim=250, use_attention=False, n_filters=2, kernel_sizes=[2,3,4,5],
                 attention_dim=100, use_embedding=True, embedding_dim=100, use_fasttext=True, freeze_emb=False,
                 max_grad_norm=5, rnn_cell_type='LSTM', max_timesteps=31, use_bow=False, vocab_size=-1,
                 learning_rate=0.001, batch_size=100, n_epochs=800, log_interval=200, store_model=True, ckpt_dir=None,
                 restore=True, store_dir="/data/rali7/Tmp/solimanz/data/models/", log_dir=".log/", name='', emb_path='',
                 skill_emb_path = ''):

        self.log_interval = log_interval
        self.batcher = batcher
        self.train_targets = train_targets
        self.test_targets = test_targets
        self.emb_path = emb_path
        self.skill_emb_path = skill_emb_path
        self.restore = restore
        self.max_grad_norm = max_grad_norm
        self.keep_prob = keep_prob
        self.use_dropout = use_dropout
        self.n_titles = n_titles
        self.n_epochs = n_epochs
        self.use_embedding= use_embedding
        self.use_fasttext = use_fasttext
        self.freeze_emb = freeze_emb
        self.rnn_cell_type = rnn_cell_type
        self.emb_dim = embedding_dim
        self.max_timesteps = max_timesteps
        self.batch_size = batch_size
        self.hidden_dim = hidden_dim
        self.lr = learning_rate
        self.use_att = use_attention
        self.att_dim = attention_dim
        self.train_data = train_data
        self.test_data = test_data
        self.store_dir = store_dir
        self.log_dir = log_dir
        self.store = store_model
        self.num_layers = num_layers
        self.use_bow = use_bow
        self.n_skills = n_skills
        self.max_skills = max_skills
        self.vocab_size = vocab_size
        self.n_filters = n_filters
        self.kernel_sizes = kernel_sizes
        self.name = name
        #title_emb_and_skills_v2_classif_vocab=-1_1_layers_cell_lr_0.001_use_emb=True_emb_dim=300_n_filters=2_kernels=3fasttext=True_freeze_emb=False_hdim=100_dropout=0.5_data_size=670328

        self.hparams = f"{name}_v2_classif_vocab={vocab_size}_{num_layers}_" \
                       f"layers_cell_lr_0.001_use_emb={use_embedding}_emb_dim={embedding_dim}_n_filters={n_filters}_kernels={len(kernel_sizes)}" \
                       f"fasttext={use_fasttext}_freeze_emb={freeze_emb}_hdim={hidden_dim}_dropout={keep_prob}_data_size={len(self.train_data)}"
        self.checkpoint_dir = os.path.join(self.store_dir, f"{self.hparams}")

        self.build_model()

    def build_model(self):
        self._predict()
        self._loss()
        self._accuracy()
        self._accuracy_last()
        self._optimize()
        self._top_2_metric()
        self._top_3_metric()
        self._top_4_metric()
        self._top_5_metric()
        self.train_summ_op = tf.summary.merge([
            self.train_loss_summ,
            #self.train_hinge_loss_summ,
            self.train_last_acc_summ,
            self.train_top_2_summ,
            self.train_top_3_summ,
            self.train_top_4_summ,
            self.train_top_5_summ])
        self.test_summ_op = tf.summary.merge([
            self.test_loss_summ,
            #self.test_hinge_loss_summ,
            self.test_last_acc_summ,
            self.test_top_2_summ,
            self.test_top_3_summ,
            self.test_top_4_summ,
            self.test_top_5_summ])
        self.writer = tf.summary.FileWriter(os.path.join(self.log_dir, self.hparams))
        self.saver = tf.train.Saver()

    def _predict(self):
        """
        Build the inference graph

        :return:
        """
        # Keep probability for the dropout
        self.dropout = tf.placeholder(tf.float32, name="dropout_prob")
        # Our list of job title sequences (padded to max_timesteps)
        self.titles_input_data = tf.placeholder(tf.int32, [None, self.max_timesteps], name="titles_input_data")

        self.skills_input = tf.placeholder(tf.int32, [None, self.max_skills], name="skills_input_data")
        # matrix that will hold the length of out sequences
        self.seq_lengths = tf.placeholder(tf.int32, [None], name="seq_lengths")
        self.targets = tf.placeholder(tf.int32, [None, self.max_timesteps, self.n_titles], name="labels")

        # Do embeddings
        with tf.device("/cpu:0"):
            skill_embs = np.load(self.skill_emb_path)
            skill_embedding = tf.get_variable(name="skill_embedding",
                                              shape=[skill_embs.shape[0], skill_embs.shape[1]],
                                              dtype=tf.float32,
                                              initializer=tf.constant_initializer(skill_embs),
                                              trainable=not self.freeze_emb)
            if self.use_embedding and not self.use_fasttext:
                title_embedding = tf.get_variable(name="title_embeddings",
                                                  shape=[self.n_titles, self.emb_dim],
                                                  dtype=tf.float32,
                                                  initializer=tf.contrib.layers.xavier_initializer(),
                                                  trainable=True)
            elif self.use_embedding and self.use_fasttext:
                embeddings_matrix = np.load(self.emb_path)
                self.emb_dim = embeddings_matrix.shape[1]

                title_embedding = tf.get_variable(name="title_embedding",
                                                  shape=[self.n_titles, self.emb_dim],
                                                  dtype=tf.float32,
                                                  initializer=tf.constant_initializer(embeddings_matrix),
                                                  trainable=not self.freeze_emb)
            else:
                title_embedding = tf.Variable(tf.eye(self.n_titles), trainable=False, name="title_one_hot_encoding")

            # tile_emb_input has shape batch_size x times steps x emb_dim

            self.title_emb_input = tf.nn.embedding_lookup(title_embedding, self.titles_input_data, name="encoded_in_seq")

            self.skill_emb_input = tf.nn.embedding_lookup(skill_embedding, self.skills_input, name="skills_lookup")

        ##################
        #   CNN Encoder  #
        ##################
        skills_shape = self.skill_emb_input.get_shape()
        print(f"Shape of skill embs: {self.skill_emb_input.get_shape()}")
        skill_embs = tf.reshape(self.skill_emb_input, [-1, skills_shape[1], skills_shape[2], 1])
        print(f"Shape of skill embs after reshape: {skill_embs.get_shape()}")

        kernel_sizes = self.kernel_sizes
        conv_layers = []
        pool_layers = []

        for i, size in enumerate(kernel_sizes):
            with tf.name_scope(f"conv-maxpool-{size}"):
                conv = tf.layers.conv2d(skill_embs,
                                        filters=self.n_filters,
                                        kernel_size=[size, skills_shape[2]],
                                        padding="valid",
                                        activation=tf.nn.relu)
                conv_shape = conv.get_shape().as_list()
                print(f"Shape of Conv Layer: {conv_shape}")
                pool = tf.layers.max_pooling2d(inputs=conv, pool_size=[conv_shape[1], 1], strides=1, padding='same')
                print(f"Shape of pool Layer: {pool.get_shape()}")
                pool_layers.append(pool)
                conv_layers.append(conv)

        pool_concat = tf.concat(pool_layers, axis=1)
        concat_shape = pool_concat.get_shape().as_list()
        print(f"Shape after concatination: {concat_shape}")

        pool_flat = tf.reshape(pool_concat, [-1, prod(concat_shape[1:])])
        print(f"Shape of flat pool: {pool_flat.get_shape()}")

        with tf.name_scope("pooling-dropout"):
            skill_context = tf.nn.dropout(pool_flat, self.keep_prob)

        c_state = tf.layers.dense(inputs=skill_context, units=self.hidden_dim, activation=tf.nn.relu)
        m_state = tf.layers.dense(inputs=skill_context, units=self.hidden_dim, activation=tf.nn.relu)
        init_states = tf.contrib.rnn.LSTMStateTuple(c_state, m_state)
        self.init_s = init_states

        #########
        #  RNN  #
        #########
        # Decide on out RNN cell type
        if self.rnn_cell_type == 'RNN':
            get_cell = tf.nn.rnn_cell.BasicRNNCell
        elif self.rnn_cell_type == 'LSTM':
            get_cell = tf.nn.rnn_cell.LSTMCell
        else: # Default to GRU
            get_cell = tf.nn.rnn_cell.GRUCell

        cell = get_cell(self.hidden_dim)
        print(cell.state_size)
        if self.use_dropout:
            cell = tf.nn.rnn_cell.DropoutWrapper(cell, output_keep_prob=self.dropout)

        self.output, self.prev_states = tf.nn.dynamic_rnn(cell,
                                                          self.title_emb_input,
                                                          initial_state=init_states,
                                                          sequence_length=self.seq_lengths,
                                                          dtype=tf.float32,
                                                          parallel_iterations=1024)

        batch_range = tf.range(tf.shape(self.output)[0])
        indices = tf.stack([batch_range, self.seq_lengths - 1], axis=1)
        # Both are shape (batch size, hidden_dim)
        self.last_target = tf.gather_nd(self.targets, indices)
        #self.last_output = tf.gather_nd(self.output, indices)

        output = tf.reshape(self.output, [-1, self.hidden_dim])

        self.logit = tf.layers.dense(output,
                                     self.n_titles,
                                     activation=None,
                                     kernel_initializer=tf.contrib.layers.xavier_initializer(),
                                     bias_initializer=tf.contrib.layers.xavier_initializer(),
                                     name="fc_logit")

        self.logit = tf.reshape(self.logit, [-1, self.max_timesteps, self.n_titles])
        self.prediction = tf.nn.softmax(self.logit, name="prediction")
        self.last_pred = tf.gather_nd(self.logit, indices)

        return self.prediction

    def _loss(self):
        with tf.name_scope("xent"):
            cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=self.logit,
                                                                           labels=tf.argmax(self.targets, 2))
            mask = tf.sequence_mask(self.seq_lengths)
            cross_entropy = tf.boolean_mask(cross_entropy, mask)
            self.loss = tf.reduce_mean(cross_entropy)

            self.train_loss_summ = tf.summary.scalar("train_xent", self.loss)
            self.test_loss_summ = tf.summary.scalar("test_xent", self.loss)
            return self.loss

    def _optimize(self):
        with tf.name_scope("train"):
            #self.optimize = tf.train.AdamOptimizer(self.lr).minimize(self.loss)
            tvars = tf.trainable_variables()
            optimizer = tf.train.AdamOptimizer(self.lr)
            grads, _ = tf.clip_by_global_norm(tf.gradients(self.loss, tvars), self.max_grad_norm)
            self.optimize = optimizer.apply_gradients(zip(grads, tvars))

            return self.optimize

    def _accuracy(self):
        with tf.name_scope("accuracy"):
            correct = tf.equal(
                tf.argmax(self.targets, axis=2, output_type=tf.int32),
                tf.argmax(self.prediction, axis=2, output_type=tf.int32))
            correct = tf.cast(correct, tf.float32)
            mask = tf.sign(tf.reduce_max(tf.abs(self.targets), reduction_indices=2))
            correct *= tf.cast(mask, tf.float32)
            # Average over actual sequence lengths.
            correct = tf.reduce_sum(correct, reduction_indices=1)
            correct /= tf.cast(self.seq_lengths, tf.float32)
            self.accuracy =  tf.reduce_mean(correct)
            self.train_acc_summ = tf.summary.scalar("training_accuracy", self.accuracy)
            self.test_acc_summ = tf.summary.scalar("test_accuracy", self.accuracy)
            return self.accuracy

    def _accuracy_last(self):
        with tf.name_scope("accuracy_last"):
            correct = tf.equal(
                tf.argmax(self.last_pred, axis=1, output_type=tf.int32),
                tf.argmax(self.last_target, axis=1, output_type=tf.int32))
            correct = tf.cast(correct, tf.float32)
            self.last_accuracy =  tf.reduce_mean(correct)
            self.train_last_acc_summ = tf.summary.scalar("train_last_acc", self.last_accuracy)
            self.test_last_acc_summ = tf.summary.scalar("test_last_accuracy", self.last_accuracy)
            return self.accuracy

    def _top_2_metric(self):
        with tf.name_scope("top_k_accs"):
            with tf.name_scope("top_2"):
                values, indices = tf.nn.top_k(self.prediction, k=2, name='top_2_op')
                labels = tf.argmax(self.targets, axis=2, output_type=tf.int32)
                labels = tf.reshape(labels, [-1, self.max_timesteps, 1])
                correct = tf.reduce_max(tf.cast(tf.equal(indices, labels), dtype=tf.int32), reduction_indices=2)
                mask = tf.sign(tf.reduce_max(tf.abs(self.targets), reduction_indices=2))
                correct *= mask
                # Average over actual sequence lengths.
                correct = tf.reduce_sum(correct, reduction_indices=1)
                correct /= self.seq_lengths

                self.top_2_acc = tf.reduce_mean(correct)
                self.train_top_2_summ = tf.summary.scalar("training_top_2_accuracy", self.top_2_acc)
                self.test_top_2_summ = tf.summary.scalar("test_top_2_accuracy", self.top_2_acc)

                return self.top_2_acc

    def _top_3_metric(self):

        with tf.name_scope("top_k_accs"):
            with tf.name_scope("top_3"):
                values, indices = tf.nn.top_k(self.prediction, k=3, name='top_3_op')
                labels = tf.argmax(self.targets, axis=2, output_type=tf.int32)
                labels = tf.reshape(labels, [-1, self.max_timesteps, 1])
                correct = tf.reduce_max(tf.cast(tf.equal(indices, labels), dtype=tf.int32), reduction_indices=2)
                mask = tf.sign(tf.reduce_max(tf.abs(self.targets), reduction_indices=2))
                correct *= mask
                # Average over actual sequence lengths.
                correct = tf.reduce_sum(correct, reduction_indices=1)
                correct /= self.seq_lengths

                self.top_3_acc = tf.reduce_mean(correct)
                self.train_top_3_summ = tf.summary.scalar("training_top_3_accuracy", self.top_3_acc)
                self.test_top_3_summ = tf.summary.scalar("test_top_3_accuracy", self.top_3_acc)

                return self.top_3_acc

    def _top_4_metric(self):

        with tf.name_scope("top_k_accs"):
            with tf.name_scope("top_4"):
                values, indices = tf.nn.top_k(self.prediction, k=4, name='top_4_op')
                labels = tf.argmax(self.targets, axis=2, output_type=tf.int32)
                labels = tf.reshape(labels, [-1, self.max_timesteps, 1])
                correct = tf.reduce_max(tf.cast(tf.equal(indices, labels), dtype=tf.int32), reduction_indices=2)
                mask = tf.sign(tf.reduce_max(tf.abs(self.targets), reduction_indices=2))
                correct *= mask
                # Average over actual sequence lengths.
                correct = tf.reduce_sum(correct, reduction_indices=1)
                correct /= self.seq_lengths

                self.top_4_acc = tf.reduce_mean(correct)
                self.train_top_4_summ = tf.summary.scalar("training_top_4_accuracy", self.top_4_acc)
                self.test_top_4_summ = tf.summary.scalar("test_top_4_accuracy", self.top_4_acc)

                return self.top_4_acc

    def _top_5_metric(self):

        with tf.name_scope("top_k_accs"):
            with tf.name_scope("top_5"):
                values, indices = tf.nn.top_k(self.prediction, k=5, name='top_5_op')
                labels = tf.argmax(self.targets, axis=2, output_type=tf.int32)
                labels = tf.reshape(labels, [-1, self.max_timesteps, 1])
                correct = tf.reduce_max(tf.cast(tf.equal(indices, labels), dtype=tf.int32), reduction_indices=2)
                mask = tf.sign(tf.reduce_max(tf.abs(self.targets), reduction_indices=2))
                correct *= mask
                # Average over actual sequence lengths.
                correct = tf.reduce_sum(correct, reduction_indices=1)
                correct /= self.seq_lengths

                self.top_5_acc = tf.reduce_mean(correct)
                self.train_top_5_summ =tf.summary.scalar("training_top_5_accuracy", self.top_5_acc)
                self.test_top_5_summ = tf.summary.scalar("test_top_5_accuracy", self.top_5_acc)

                return self.top_5_acc


    # def _loss(self):
    #     with tf.name_scope("xent"):
    #         cross_entropy = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=self.logit,
    #                                                                        labels=tf.argmax(self.last_target, 1))
    #         self.loss = tf.reduce_mean(cross_entropy)
    #
    #         self.train_loss_summ = tf.summary.scalar("train_xent", self.loss)
    #         self.test_loss_summ = tf.summary.scalar("test_xent", self.loss)
    #
    #     return self.loss
    #
    # def _optimize(self):
    #     with tf.name_scope("train"):
    #         #self.optimize = tf.train.AdamOptimizer(self.lr).minimize(self.loss)
    #         tvars = tf.trainable_variables()
    #         optimizer = tf.train.AdamOptimizer(self.lr)
    #         grads, _ = tf.clip_by_global_norm(tf.gradients(self.loss, tvars), self.max_grad_norm)
    #         self.optimize = optimizer.apply_gradients(zip(grads, tvars))
    #
    #         return self.optimize
    #
    # def _accuracy(self):
    #     with tf.name_scope("accuracy"):
    #         correct = tf.equal(
    #             tf.argmax(self.prediction, axis=1, output_type=tf.int32),
    #             tf.argmax(self.last_target, axis=1, output_type=tf.int32))
    #         correct = tf.cast(correct, tf.float32)
    #         self.accuracy =  tf.reduce_mean(correct)
    #         self.train_last_acc_summ = tf.summary.scalar("train_last_acc", self.accuracy)
    #         self.test_last_acc_summ = tf.summary.scalar("test_last_accuracy", self.accuracy)
    #         return self.accuracy
    #
    # def _top_2_metric(self):
    #     with tf.name_scope("top_k_accs"):
    #         with tf.name_scope("top_2"):
    #             values, indices = tf.nn.top_k(self.prediction, k=2, name='top_2_op')
    #             labels = tf.argmax(self.last_target, axis=1, output_type=tf.int32)
    #             labels = tf.reshape(labels, [-1, 1])
    #             correct = tf.reduce_max(tf.cast(tf.equal(indices, labels), dtype=tf.int32), reduction_indices=1)
    #
    #             self.top_2_acc = tf.reduce_mean(tf.cast(correct, dtype=tf.float32))
    #
    #             self.train_top_2_summ = tf.summary.scalar("training_top_2_accuracy", self.top_2_acc)
    #             self.test_top_2_summ = tf.summary.scalar("test_top_2_accuracy", self.top_2_acc)
    #
    #             return self.top_2_acc
    #
    # def _top_3_metric(self):
    #
    #     with tf.name_scope("top_k_accs"):
    #         with tf.name_scope("top_3"):
    #             values, indices = tf.nn.top_k(self.prediction, k=3, name='top_3_op')
    #             labels = tf.argmax(self.last_target, axis=1, output_type=tf.int32)
    #             labels = tf.reshape(labels, [-1, 1])
    #             correct = tf.reduce_max(tf.cast(tf.equal(indices, labels), dtype=tf.int32), reduction_indices=1)
    #
    #             self.top_3_acc = tf.reduce_mean(tf.cast(correct, dtype=tf.float32))
    #             self.train_top_3_summ = tf.summary.scalar("training_top_3_accuracy", self.top_3_acc)
    #             self.test_top_3_summ = tf.summary.scalar("test_top_3_accuracy", self.top_3_acc)
    #
    #             return self.top_3_acc
    #
    # def _top_4_metric(self):
    #
    #     with tf.name_scope("top_k_accs"):
    #         with tf.name_scope("top_4"):
    #             values, indices = tf.nn.top_k(self.prediction, k=4, name='top_4_op')
    #             labels = tf.argmax(self.last_target, axis=1, output_type=tf.int32)
    #             labels = tf.reshape(labels, [-1, 1])
    #             correct = tf.reduce_max(tf.cast(tf.equal(indices, labels), dtype=tf.int32), reduction_indices=1)
    #
    #             self.top_4_acc = tf.reduce_mean(tf.cast(correct, dtype=tf.float32))
    #             self.train_top_4_summ = tf.summary.scalar("training_top_4_accuracy", self.top_4_acc)
    #             self.test_top_4_summ = tf.summary.scalar("test_top_4_accuracy", self.top_4_acc)
    #
    #             return self.top_4_acc
    #
    # def _top_5_metric(self):
    #
    #     with tf.name_scope("top_k_accs"):
    #         with tf.name_scope("top_5"):
    #             values, indices = tf.nn.top_k(self.prediction, k=5, name='top_5_op')
    #             labels = tf.argmax(self.last_target, axis=1, output_type=tf.int32)
    #             labels = tf.reshape(labels, [-1, 1])
    #             correct = tf.reduce_max(tf.cast(tf.equal(indices, labels), dtype=tf.int32), reduction_indices=1)
    #
    #             self.top_5_acc = tf.reduce_mean(tf.cast(correct, dtype=tf.float32))
    #             self.train_top_5_summ =tf.summary.scalar("training_top_5_accuracy", self.top_5_acc)
    #             self.test_top_5_summ = tf.summary.scalar("test_top_5_accuracy", self.top_5_acc)
    #
    #             return self.top_5_acc

    def train(self):

        print("Creating batchers")
        # batch_size, step_num, max_skills, data, n_classes, n_skills,
        train_batcher = self.batcher(batch_size=self.batch_size, step_num=self.max_timesteps,
                                     max_skills=self.max_skills, data=self.train_data,
                                     n_classes=self.n_titles, n_skills=self.n_skills)
        test_batcher = self.batcher(batch_size=self.batch_size, step_num=self.max_timesteps,
                                    max_skills=self.max_skills, data=self.test_data,
                                    n_classes=self.n_titles, n_skills=self.n_skills)

        # Assume that you have 12GB of GPU memory and want to allocate ~4GB:
        gpu_config = tf.ConfigProto(log_device_placement=False)
        gpu_config.gpu_options.allow_growth = True

        with tf.Session(config=gpu_config) as sess:

            sess.run(tf.global_variables_initializer())
            if self.load(sess, self.checkpoint_dir):
                print(" [*] Load SUCCESS")
            else:
                print(" [!] Load failed...")

            self.writer.add_graph(sess.graph)

            for e in range(self.n_epochs):
                start_time = time()
                batch = 0
                for b in range(train_batcher.max_batch_num):

                    with tf.device("/cpu:0"):
                        title_seq, seq_lengths, target, skills = train_batcher.next()

                    loss, _, acc, top_2_acc, top_3_acc, top_4_acc, top_5_acc, summary = sess.run([
                        self.loss,
                        self.optimize,
                        self.accuracy,
                        self.top_2_acc,
                        self.top_3_acc,
                        self.top_4_acc,
                        self.top_5_acc,
                        self.train_summ_op
                    ],
                        {
                            self.titles_input_data: title_seq,
                            self.seq_lengths: seq_lengths,
                            self.targets: target,
                            self.skills_input: skills,
                            self.dropout: self.keep_prob
                        })

                    if batch % self.log_interval == 0 and batch > 0:
                        elapsed = time() - start_time
                        print(
                            f'| epoch {e} | {train_batcher.batch_num}/{train_batcher.max_batch_num} batches | lr {self.lr} | '
                            f'ms/batch {elapsed * 1000 / self.log_interval:.2f} | loss {loss:.3f} | acc: {acc*100:.2f} |'
                            f' top 2 acc: {top_2_acc*100:.2f} | top 3 acc: {top_3_acc*100:.2f} | top 4 acc: {top_4_acc*100:.2f}'
                            f' | top 5 acc: {top_5_acc*100:.2f}')

                        start_time = time()

                    batch += 1

                print(f"Epoch:, {(e + 1)}")

                avg_acc = []
                tst_loss = []
                avg_top_2 = []
                avg_top_3 = []
                avg_top_4 = []
                avg_top_5 = []

                for tb in range(test_batcher.max_batch_num):
                    with tf.device("/cpu:0"):
                        test_title_seq, test_seq_lengths, test_target, skills = test_batcher.next()

                    test_acc, test_loss, test_top_2, test_top_3, test_top_4, test_top_5, test_summ, pred = sess.run([
                        self.accuracy,
                        self.loss,
                        self.top_2_acc,
                        self.top_3_acc,
                        self.top_4_acc,
                        self.top_5_acc,
                        self.test_summ_op,
                        self.prediction
                    ],
                        {
                            self.titles_input_data: test_title_seq,
                            self.seq_lengths: test_seq_lengths,
                            self.targets: test_target,
                            self.skills_input: skills,
                            self.dropout: 1.0
                        })

                    if test_acc > 0:
                        avg_acc.append(test_acc)
                    if test_top_2 > 0:
                        avg_top_2.append(test_top_2)
                    if test_top_3 > 0:
                        avg_top_3.append(test_top_3)
                    if test_top_4 > 0:
                        avg_top_4.append(test_top_4)
                    if test_top_5 > 0:
                        avg_top_5.append(test_top_5)
                    if test_loss > 0:
                        tst_loss.append(test_loss)

                    #print_dists(self.titles_to_id, test_seq_lengths, test_title_seq, pred, test_target, f_name=self.hparams)
                    self.writer.add_summary(test_summ, tb)

                print(f"Loss on test: {sum(tst_loss)/len(tst_loss):.2f}")
                print(f"Accuracy on test: {sum(avg_acc)/len(avg_acc)*100:.2f}")
                print(f"Top 2 accuracy on test: {sum(avg_top_2)/len(avg_top_2)*100:.2f}")
                print(f"Top 3 accuracy on test: {sum(avg_top_3)/len(avg_top_3)*100:.2f}")
                print(f"Top 4 accuracy on test: {sum(avg_top_4)/len(avg_top_4)*100:.2f}")
                print(f"Top 5 accuracy on test: {sum(avg_top_5)/len(avg_top_5)*100:.2f}")
                if self.store and e % 5 == 0:
                    save_path = self.save(sess, self.checkpoint_dir, e)
                    print("model saved in file: %s" % save_path)

    def test(self):

        base_path = "/data/rali7/Tmp/solimanz/data/lstm_cnn_predictions"
        tsne_path = "/data/rali7/Tmp/solimanz/data/tSNE"

        if self.n_titles == 551:
            path = os.path.join(base_path, 'top550')
        elif self.n_titles >= 7000:
            path = os.path.join(base_path, 'reduced7k')
        else:
            print("Number of job title labels doesn't match 550 or 7000")
            return

        print("Creating batchers")
        test_batcher = self.batcher(batch_size=self.batch_size, step_num=self.max_timesteps,
                                    max_skills=self.max_skills, data=self.test_data,
                                    n_classes=self.n_titles, n_skills=self.n_skills)

        # Assume that you have 12GB of GPU memory and want to allocate ~4GB:
        gpu_config = tf.ConfigProto(log_device_placement=False)
        gpu_config.gpu_options.allow_growth = True

        with tf.Session(config=gpu_config) as sess:

            sess.run(tf.global_variables_initializer())
            if self.load(sess, self.checkpoint_dir):
                print(" [*] Load SUCCESS")
            else:
                print(" [!] Load failed...")
                return

            print(f"Number of batches: {test_batcher.max_batch_num}")
            print(f"Size of dataset: {len(self.test_data)}")
            print(f"Batch Size: {self.batch_size}")

            for tb in range(test_batcher.max_batch_num):

                print(f"Batch #{tb}")
                with tf.device("/cpu:0"):
                    title_seq, seq_lengths, target, skills = test_batcher.next()

                pred, skillset, output, prev_states = sess.run([self.prediction, self.init_s, self.output, self.prev_states],
                                {
                                    self.titles_input_data: title_seq,
                                    self.seq_lengths: seq_lengths,
                                    self.targets: target,
                                    self.skills_input: skills,
                                    self.dropout: 1.0
                                })

                #np.save(os.path.join(path, 'predictions', f'predictions_batch_{tb}.npy'), pred[0])
                #np.save(os.path.join(path, 'seq_lengths', f'seq_lengths_batch_{tb}.npy'), seq_lengths)
                np.save(os.path.join(tsne_path, f'skillset_{tb}.npy'), skillset)
                np.save(os.path.join(tsne_path, f'output_{tb}.npy'), output)
                np.save(os.path.join(tsne_path, f'state_{tb}.npy'), prev_states)

    def save(self, sess, checkpoint_dir, step):
        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)

        return self.saver.save(sess,
                        os.path.join(checkpoint_dir, self.hparams),
                        global_step=step)

    def load(self, sess, checkpoint_dir):
        print(" [*] Reading checkpoints...")

        ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
        if ckpt and ckpt.model_checkpoint_path:
            self.saver.restore(sess, ckpt.model_checkpoint_path)
            return True
        else:
            return False

    def tSNE(self, dataset, name):

        gpu_config = tf.ConfigProto(log_device_placement=False)
        gpu_config.gpu_options.allow_growth = True

        with tf.Session(config=gpu_config) as sess:

            sess.run(tf.global_variables_initializer())
            if self.load(sess, self.checkpoint_dir):
                print(" [*] Load SUCCESS")
            else:
                print(" [!] Load failed...")
                return

            tvars = tf.trainable_variables()

            graph = tf.get_default_graph()
            print([v.name for v in tvars])
            job_emb = [graph.get_tensor_by_name(v.name).eval() for v in tvars if v.name == "title_embedding:0"][0]
            skill_emb = [graph.get_tensor_by_name(v.name).eval() for v in tvars if v.name == "skill_embedding:0"][0]

            np.save(f"/data/rali7/Tmp/solimanz/data/tSNE/{name}_job_title_emb.npy", job_emb)
            np.save(f"/data/rali7/Tmp/solimanz/data/tSNE/{name}_skills_emb.npy", job_emb)


